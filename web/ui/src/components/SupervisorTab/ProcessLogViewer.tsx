/**
 * ProcessLogViewer - Interactive terminal for supervised processes
 *
 * Shows streaming stdout/stderr output from a process with:
 * - Initial history fetch on open (most recent entries)
 * - Real-time streaming of new output via WebSocket events
 * - ANSI escape code rendering (colors, bold, etc.)
 * - Auto-scroll to bottom
 * - Timestamp display
 * - Copy to clipboard
 * - Input field for sending stdin to the process
 */

import React, { useEffect, useRef, useState, useCallback, memo, useMemo } from 'react';
import type { FormEvent } from 'react';
import type { ProcessOutput, ProcessInfo, ProcessLogEntry as ServerLogEntry } from '../../../../generated/balloons-client';
import type { SupervisorStateServiceClient } from '../../../../generated/client';

// ANSI color code to CSS color mapping
const ANSI_COLORS: Record<number, string> = {
  30: '#000000', 31: '#cc0000', 32: '#4e9a06', 33: '#c4a000',
  34: '#3465a4', 35: '#75507b', 36: '#06989a', 37: '#d3d7cf',
  90: '#555753', 91: '#ef2929', 92: '#8ae234', 93: '#fce94f',
  94: '#729fcf', 95: '#ad7fa8', 96: '#34e2e2', 97: '#eeeeec',
};

const ANSI_BG_COLORS: Record<number, string> = {
  40: '#000000', 41: '#cc0000', 42: '#4e9a06', 43: '#c4a000',
  44: '#3465a4', 45: '#75507b', 46: '#06989a', 47: '#d3d7cf',
  100: '#555753', 101: '#ef2929', 102: '#8ae234', 103: '#fce94f',
  104: '#729fcf', 105: '#ad7fa8', 106: '#34e2e2', 107: '#eeeeec',
};

interface AnsiSpan {
  text: string;
  style: React.CSSProperties;
}

/**
 * Parse ANSI escape codes and return styled spans.
 * Handles colors, bold, dim, italic, underline, and reset codes.
 * Strips cursor movement codes (they don't make sense in a log viewer).
 */
function parseAnsi(text: string): AnsiSpan[] {
  const spans: AnsiSpan[] = [];
  let currentStyle: React.CSSProperties = {};
  let lastIndex = 0;

  // Match ANSI escape sequences: ESC [ ... m (SGR) or other CSI sequences
  const ansiRegex = /\x1b\[([0-9;]*)([A-Za-z])/g;
  let match;

  while ((match = ansiRegex.exec(text)) !== null) {
    // Add text before this escape sequence
    if (match.index > lastIndex) {
      const content = text.slice(lastIndex, match.index);
      if (content) {
        spans.push({ text: content, style: { ...currentStyle } });
      }
    }

    const params = match[1];
    const command = match[2];

    // Only process SGR (Select Graphic Rendition) codes - command 'm'
    if (command === 'm') {
      const codes = params ? params.split(';').map(Number) : [0];
      for (const code of codes) {
        if (code === 0) {
          // Reset
          currentStyle = {};
        } else if (code === 1) {
          currentStyle.fontWeight = 'bold';
        } else if (code === 2) {
          currentStyle.opacity = 0.7;
        } else if (code === 3) {
          currentStyle.fontStyle = 'italic';
        } else if (code === 4) {
          currentStyle.textDecoration = 'underline';
        } else if (code === 22) {
          delete currentStyle.fontWeight;
          delete currentStyle.opacity;
        } else if (code === 23) {
          delete currentStyle.fontStyle;
        } else if (code === 24) {
          delete currentStyle.textDecoration;
        } else if (code === 39) {
          delete currentStyle.color;
        } else if (code === 49) {
          delete currentStyle.backgroundColor;
        } else if (ANSI_COLORS[code]) {
          currentStyle.color = ANSI_COLORS[code];
        } else if (ANSI_BG_COLORS[code]) {
          currentStyle.backgroundColor = ANSI_BG_COLORS[code];
        }
      }
    }
    // Other CSI commands (cursor movement, etc.) are silently stripped

    lastIndex = match.index + match[0].length;
  }

  // Add remaining text
  if (lastIndex < text.length) {
    spans.push({ text: text.slice(lastIndex), style: { ...currentStyle } });
  }

  return spans;
}

/** Render text with ANSI escape codes as styled spans */
function AnsiText({ text }: { text: string }) {
  const spans = useMemo(() => parseAnsi(text), [text]);

  if (spans.length === 0) {
    return null;
  }

  const firstSpan = spans[0];
  if (spans.length === 1 && firstSpan && Object.keys(firstSpan.style).length === 0) {
    // No styling needed, return plain text
    return <>{firstSpan.text}</>;
  }

  return (
    <>
      {spans.map((span, i) => (
        <span key={i} style={span.style}>{span.text}</span>
      ))}
    </>
  );
}

interface ProcessLogEntry {
  ts: number;
  source: 'stdout' | 'stderr' | 'system' | 'stdin';
  content: string;
}

interface ProcessLogViewerProps {
  /** Process to show logs for */
  process: ProcessInfo;
  /** WebSocket client for subscribing to events */
  client: SupervisorStateServiceClient;
  /** Called when the viewer should close */
  onClose: () => void;
  /** Maximum log entries to keep in memory */
  maxEntries?: number;
  /** Number of history entries to fetch on open */
  initialHistoryLimit?: number;
}

export const ProcessLogViewer = memo(function ProcessLogViewer({
  process,
  client,
  onClose,
  maxEntries = 1000,
  initialHistoryLimit = 200,
}: ProcessLogViewerProps) {
  const [logs, setLogs] = useState<ProcessLogEntry[]>([]);
  const [autoScroll, setAutoScroll] = useState(true);
  const [inputValue, setInputValue] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const logContainerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // Track the latest timestamp we've seen to avoid duplicates
  const latestTsRef = useRef<number>(0);

  // Fetch initial history when component mounts
  useEffect(() => {
    let cancelled = false;

    async function fetchHistory() {
      try {
        setIsLoadingHistory(true);
        setHistoryError(null);

        const batch = await client.getProcessOutput(
          process.processId,
          initialHistoryLimit,
          0, // offset
          undefined // no source filter
        );

        if (cancelled) return;

        if (batch.entries && batch.entries.length > 0) {
          const entries: ProcessLogEntry[] = batch.entries.map((e: ServerLogEntry) => ({
            ts: e.ts,
            source: e.source as 'stdout' | 'stderr' | 'system' | 'stdin',
            content: e.content,
          }));

          // Track the latest timestamp to avoid duplicates from streaming
          const maxTs = Math.max(...entries.map(e => e.ts));
          latestTsRef.current = maxTs;

          setLogs(entries);
        }
      } catch (error) {
        if (cancelled) return;
        console.error('Failed to fetch process history:', error);
        setHistoryError(error instanceof Error ? error.message : 'Failed to load history');
      } finally {
        if (!cancelled) {
          setIsLoadingHistory(false);
        }
      }
    }

    fetchHistory();

    return () => {
      cancelled = true;
    };
  }, [client, process.processId, initialHistoryLimit]);

  // Subscribe to process output events for real-time updates
  useEffect(() => {
    const unsubscribe = client.processOutput((output: ProcessOutput) => {
      // Only show output for this process
      if (output.processId !== process.processId) {
        return;
      }

      // Skip if we've already seen this entry (from history fetch)
      if (output.ts <= latestTsRef.current) {
        return;
      }

      // Update the latest timestamp
      latestTsRef.current = output.ts;

      setLogs((prevLogs) => {
        const newEntry: ProcessLogEntry = {
          ts: output.ts,
          source: output.source as 'stdout' | 'stderr' | 'system' | 'stdin',
          content: output.content,
        };

        // Keep only the last maxEntries
        const newLogs = [...prevLogs, newEntry];
        if (newLogs.length > maxEntries) {
          return newLogs.slice(-maxEntries);
        }
        return newLogs;
      });
    });

    return unsubscribe;
  }, [client, process.processId, maxEntries]);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  // Handle scroll to detect if user scrolled up
  const handleScroll = useCallback(() => {
    if (!logContainerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = logContainerRef.current;
    // If user is near the bottom (within 50px), enable auto-scroll
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 50;
    setAutoScroll(isNearBottom);
  }, []);

  // Copy logs to clipboard
  const handleCopy = useCallback(() => {
    const text = logs
      .map((entry) => {
        const time = new Date(entry.ts * 1000).toLocaleTimeString();
        return `[${time}] ${entry.source}: ${entry.content}`;
      })
      .join('\n');
    navigator.clipboard.writeText(text);
  }, [logs]);

  // Clear logs
  const handleClear = useCallback(() => {
    setLogs([]);
  }, []);

  // Send input to process stdin
  const handleSendInput = useCallback(async (e: FormEvent) => {
    e.preventDefault();
    if (!inputValue.trim() || isSending) return;

    const data = inputValue;
    setInputValue('');
    setIsSending(true);

    try {
      const result = await client.sendProcessInput(process.processId, data);
      if (!result.success) {
        console.error('Failed to send input:', result.error);
        // Add error to log display
        setLogs((prevLogs) => [
          ...prevLogs,
          {
            ts: Date.now() / 1000,
            source: 'system' as const,
            content: `Failed to send input: ${result.error}`,
          },
        ]);
      }
    } catch (error) {
      console.error('Error sending input:', error);
      setLogs((prevLogs) => [
        ...prevLogs,
        {
          ts: Date.now() / 1000,
          source: 'system' as const,
          content: `Error sending input: ${error}`,
        },
      ]);
    } finally {
      setIsSending(false);
      inputRef.current?.focus();
    }
  }, [client, process.processId, inputValue, isSending]);

  // Format timestamp
  const formatTime = (ts: number): string => {
    return new Date(ts * 1000).toLocaleTimeString();
  };

  const isRunning = process.status === 'running';

  return (
    <div className="process-log-viewer">
      <div className="process-log-viewer__header">
        <div className="process-log-viewer__title">
          <span className="process-log-viewer__process-name">
            {process.name || process.processId.slice(0, 8)}
          </span>
          <span className="process-log-viewer__process-status">
            ({process.status})
          </span>
        </div>
        <div className="process-log-viewer__actions">
          <button
            className="process-log-viewer__action-btn"
            onClick={handleCopy}
            title="Copy logs to clipboard"
          >
            Copy
          </button>
          <button
            className="process-log-viewer__action-btn"
            onClick={handleClear}
            title="Clear log display"
          >
            Clear
          </button>
          <button
            className="process-log-viewer__action-btn process-log-viewer__action-btn--close"
            onClick={onClose}
            title="Close log viewer"
          >
            Close
          </button>
        </div>
      </div>

      <div className="process-log-viewer__command">
        <code>{process.command}</code>
      </div>

      <div
        ref={logContainerRef}
        className="process-log-viewer__logs"
        onScroll={handleScroll}
      >
        {isLoadingHistory ? (
          <div className="process-log-viewer__loading">
            Loading history...
          </div>
        ) : historyError ? (
          <div className="process-log-viewer__error">
            Error: {historyError}
          </div>
        ) : logs.length === 0 ? (
          <div className="process-log-viewer__empty">
            No output yet
          </div>
        ) : (
          logs.map((entry, index) => (
            <div
              key={`${entry.ts}-${index}`}
              className={`process-log-viewer__entry process-log-viewer__entry--${entry.source}`}
            >
              <span className="process-log-viewer__timestamp">
                {formatTime(entry.ts)}
              </span>
              <span className="process-log-viewer__source">
                {entry.source}
              </span>
              <span className="process-log-viewer__content">
                <AnsiText text={entry.content} />
              </span>
            </div>
          ))
        )}
      </div>

      {/* Input field for stdin */}
      {isRunning && (
        <form className="process-log-viewer__input-form" onSubmit={handleSendInput}>
          <input
            ref={inputRef}
            type="text"
            className="process-log-viewer__input"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Type input and press Enter..."
            disabled={isSending}
            autoFocus
          />
          <button
            type="submit"
            className="process-log-viewer__send-btn"
            disabled={isSending || !inputValue.trim()}
            title="Send input to process"
          >
            {isSending ? '...' : 'Send'}
          </button>
        </form>
      )}

      <div className="process-log-viewer__footer">
        <label className="process-log-viewer__autoscroll">
          <input
            type="checkbox"
            checked={autoScroll}
            onChange={(e) => setAutoScroll(e.target.checked)}
          />
          Auto-scroll
        </label>
        <span className="process-log-viewer__count">
          {logs.length} entries
        </span>
      </div>
    </div>
  );
});

export default ProcessLogViewer;
