/**
 * ProcessLogViewer - Real-time log viewer for supervised processes
 *
 * Shows streaming stdout/stderr output from a process with:
 * - Color-coded output (stdout vs stderr)
 * - Auto-scroll to bottom
 * - Timestamp display
 * - Copy to clipboard
 */

import React, { useEffect, useRef, useState, useCallback, memo } from 'react';
import type { ProcessOutput, ProcessInfo } from '../../../../generated/balloons-client';
import type { SupervisorStateServiceClient } from '../../../../generated/client';

interface ProcessLogEntry {
  ts: number;
  source: 'stdout' | 'stderr' | 'system';
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
}

export const ProcessLogViewer = memo(function ProcessLogViewer({
  process,
  client,
  onClose,
  maxEntries = 1000,
}: ProcessLogViewerProps) {
  const [logs, setLogs] = useState<ProcessLogEntry[]>([]);
  const [autoScroll, setAutoScroll] = useState(true);
  const logContainerRef = useRef<HTMLDivElement>(null);

  // Subscribe to process output events
  useEffect(() => {
    const unsubscribe = client.processOutput((output: ProcessOutput) => {
      // Only show output for this process
      if (output.processId !== process.processId) {
        return;
      }

      setLogs((prevLogs) => {
        const newEntry: ProcessLogEntry = {
          ts: output.ts,
          source: output.source as 'stdout' | 'stderr' | 'system',
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

  // Format timestamp
  const formatTime = (ts: number): string => {
    return new Date(ts * 1000).toLocaleTimeString();
  };

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
        {logs.length === 0 ? (
          <div className="process-log-viewer__empty">
            Waiting for output...
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
                {entry.content}
              </span>
            </div>
          ))
        )}
      </div>

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
