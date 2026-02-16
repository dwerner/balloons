/**
 * Debug Pane Types
 *
 * Type definitions for debug log entries and levels,
 * mirroring the Python LogLevel and LogEntry from core/debug_log.py.
 */

/** Log level severity (matches Python LogLevel enum) */
export type LogLevel = 'error' | 'warning' | 'info' | 'perf' | 'debug' | 'trace';

/** Severity ordering for log levels (higher = more severe) */
export const LOG_LEVEL_SEVERITY: Record<LogLevel, number> = {
  error: 50,
  warning: 40,
  info: 30,
  perf: 25,
  debug: 20,
  trace: 10,
};

/** Single-letter labels for log levels */
export const LOG_LEVEL_LABELS: Record<LogLevel, string> = {
  error: 'E',
  warning: 'W',
  info: 'I',
  perf: 'P',
  debug: 'D',
  trace: 'T',
};

/** All log levels in order from most verbose to most severe */
export const LOG_LEVELS: LogLevel[] = ['trace', 'debug', 'perf', 'info', 'warning', 'error'];

/**
 * A single debug log entry.
 * Matches the Python LogEntry dataclass structure.
 */
export interface LogEntry {
  /** Monotonic sequence number for ordering */
  seq: number;
  /** Log severity level */
  level: LogLevel;
  /** Log message */
  message: string;
  /** Timestamp string (HH:MM:SS.mmm) */
  timestamp: string;
  /** Optional session ID */
  sessionId?: string;
  /** Optional category (process, stderr, json, event, stream) */
  category?: string;
  /** Optional additional details */
  details?: Record<string, unknown>;
  /** Optional run ID (groups entries by Claude process) */
  runId?: string;
}

/**
 * Debug log event data (for WebSocket subscription)
 */
export interface DebugLogEventData {
  eventType: 'log_entry' | 'level_changed' | 'cleared';
  entry?: LogEntry;
  level?: LogLevel;
}
