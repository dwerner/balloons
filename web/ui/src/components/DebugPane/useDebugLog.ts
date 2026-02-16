import { useState, useEffect, useCallback, useRef } from 'react';
import type { LogEntry, LogLevel } from './DebugPaneTypes';
import { LOG_LEVEL_SEVERITY } from './DebugPaneTypes';

/**
 * Options for the useDebugLog hook.
 */
export interface UseDebugLogOptions {
  /** Maximum number of entries to keep in memory (default: 500) */
  maxEntries?: number;
  /** Initial minimum log level filter */
  initialMinLevel?: LogLevel;
  /** WebSocket URL for real-time log subscription */
  wsUrl?: string;
  /** Initial entries to load */
  initialEntries?: LogEntry[];
}

/**
 * Return type for the useDebugLog hook.
 */
export interface UseDebugLogReturn {
  /** All log entries (unfiltered) */
  entries: LogEntry[];
  /** Filtered entries based on minimum level */
  filteredEntries: LogEntry[];
  /** Current minimum log level */
  minLevel: LogLevel;
  /** Set the minimum log level filter */
  setMinLevel: (level: LogLevel) => void;
  /** Clear all entries */
  clearEntries: () => void;
  /** Add a new entry manually */
  addEntry: (entry: LogEntry) => void;
  /** Count of error entries */
  errorCount: number;
  /** Whether connected to WebSocket */
  isConnected: boolean;
}

/**
 * Hook for managing debug log state and WebSocket subscription.
 *
 * Provides:
 * - Log entry storage with pruning
 * - Level filtering
 * - WebSocket subscription for real-time updates
 * - Entry management (add, clear)
 *
 * @example
 * ```tsx
 * const {
 *   entries,
 *   filteredEntries,
 *   minLevel,
 *   setMinLevel,
 *   clearEntries,
 *   errorCount,
 * } = useDebugLog({
 *   maxEntries: 500,
 *   initialMinLevel: 'debug',
 * });
 *
 * return (
 *   <DebugPane
 *     entries={filteredEntries}
 *     onMinLevelChange={setMinLevel}
 *     onClear={clearEntries}
 *   />
 * );
 * ```
 */
export function useDebugLog(options: UseDebugLogOptions = {}): UseDebugLogReturn {
  const {
    maxEntries = 500,
    initialMinLevel = 'debug',
    wsUrl,
    initialEntries = [],
  } = options;

  const [entries, setEntries] = useState<LogEntry[]>(initialEntries);
  const [minLevel, setMinLevel] = useState<LogLevel>(initialMinLevel);
  const [isConnected, setIsConnected] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const seqRef = useRef<number>(0);

  // Calculate error count
  const errorCount = entries.filter((e) => e.level === 'error').length;

  // Filter entries by minimum level
  const minSeverity = LOG_LEVEL_SEVERITY[minLevel];
  const filteredEntries = entries.filter(
    (e) => LOG_LEVEL_SEVERITY[e.level] >= minSeverity
  );

  // Add entry with sequence tracking and pruning
  const addEntry = useCallback((entry: LogEntry) => {
    setEntries((prev) => {
      // Skip if we've already seen this sequence number
      if (entry.seq <= seqRef.current) {
        return prev;
      }
      seqRef.current = entry.seq;

      // Add new entry
      const next = [...prev, entry];

      // Prune if over limit
      if (next.length > maxEntries) {
        return next.slice(-maxEntries);
      }
      return next;
    });
  }, [maxEntries]);

  // Clear all entries
  const clearEntries = useCallback(() => {
    setEntries([]);
    seqRef.current = 0;
  }, []);

  // WebSocket subscription
  useEffect(() => {
    if (!wsUrl) {
      return;
    }

    const connect = () => {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        // Subscribe to debug log events
        ws.send(JSON.stringify({
          id: 'debug-log-subscribe',
          method: 'subscribeDebugLog',
          params: {},
        }));
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);

          // Handle debug log events
          if (msg.event === 'debugLogEntry' && msg.data?.entry) {
            addEntry(msg.data.entry as LogEntry);
          } else if (msg.event === 'debugLogCleared') {
            clearEntries();
          }
        } catch {
          // Ignore parse errors
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        wsRef.current = null;
      };

      ws.onerror = () => {
        setIsConnected(false);
      };
    };

    connect();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [wsUrl, addEntry, clearEntries]);

  return {
    entries,
    filteredEntries,
    minLevel,
    setMinLevel,
    clearEntries,
    addEntry,
    errorCount,
    isConnected,
  };
}
