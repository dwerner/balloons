/**
 * LogsTab - View server debug log entries from in-memory ring buffers
 *
 * Features:
 * - Category selector (8 core categories + _default)
 * - Level filter (error/warning/info/debug/trace/perf)
 * - Auto-refresh toggle
 * - Expandable entries with details JSON
 *
 * URL ROUTING INTEGRATION:
 * - Category selection could update URL to #/logs/:category
 * - Level filter could be a query param: #/logs/runner?level=error
 * - See docs/url-routing.md for the full routing design
 */

import React, { useState, useEffect, useCallback, useRef, memo } from 'react';
import type { DebugLogServiceClient } from '../../../../generated/client';
import type { LogEntryOutput, BufferStats } from '../../../../generated/types';
import './LogsTab.css';

// 8 core categories + _default for unmigrated entries
const LOG_CATEGORIES = [
  { id: 'runner', label: 'Runner' },
  { id: 'api', label: 'API' },
  { id: 'session', label: 'Session' },
  { id: 'storage', label: 'Storage' },
  { id: 'supervisor', label: 'Supervisor' },
  { id: 'lifecycle', label: 'Lifecycle' },
  { id: 'perf', label: 'Perf' },
  { id: 'client', label: 'Client' },
  { id: '_default', label: 'Other' },
] as const;

const LOG_LEVELS = [
  { id: '', label: 'All' },
  { id: 'error', label: 'Error' },
  { id: 'warning', label: 'Warning' },
  { id: 'info', label: 'Info' },
  { id: 'perf', label: 'Perf' },
  { id: 'debug', label: 'Debug' },
  { id: 'trace', label: 'Trace' },
] as const;

interface LogsTabProps {
  debugLogClient?: DebugLogServiceClient;
  isConnected: boolean;
}

export const LogsTab = memo(function LogsTab({
  debugLogClient,
  isConnected,
}: LogsTabProps) {
  const [category, setCategory] = useState<string>('runner');
  const [level, setLevel] = useState<string>('');
  const [entries, setEntries] = useState<LogEntryOutput[]>([]);
  const [bufferStats, setBufferStats] = useState<BufferStats[]>([]);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [expandedEntries, setExpandedEntries] = useState<Set<number>>(new Set());
  const entriesRef = useRef<HTMLDivElement>(null);

  // Fetch entries for the selected category
  const fetchEntries = useCallback(async () => {
    if (!debugLogClient || !isConnected) return;

    setIsLoading(true);
    try {
      const result = await debugLogClient.query(category, 100, level || undefined);
      setEntries(result.entries);
    } catch (err) {
      console.error('Failed to fetch log entries:', err);
    } finally {
      setIsLoading(false);
    }
  }, [debugLogClient, isConnected, category, level]);

  // Fetch buffer stats
  const fetchStats = useCallback(async () => {
    if (!debugLogClient || !isConnected) return;

    try {
      const stats = await debugLogClient.getBufferStats();
      setBufferStats(stats);
    } catch (err) {
      console.error('Failed to fetch buffer stats:', err);
    }
  }, [debugLogClient, isConnected]);

  // Initial load
  useEffect(() => {
    fetchEntries();
    fetchStats();
  }, [fetchEntries, fetchStats]);

  // Auto-refresh
  useEffect(() => {
    if (!autoRefresh || !debugLogClient || !isConnected) return;

    const interval = setInterval(() => {
      fetchEntries();
      fetchStats();
    }, 2000);

    return () => clearInterval(interval);
  }, [autoRefresh, fetchEntries, fetchStats, debugLogClient, isConnected]);

  // Toggle entry expansion
  const toggleEntry = useCallback((seq: number) => {
    setExpandedEntries(prev => {
      const next = new Set(prev);
      if (next.has(seq)) {
        next.delete(seq);
      } else {
        next.add(seq);
      }
      return next;
    });
  }, []);

  // Get count for a category
  const getCategoryCount = useCallback((catId: string) => {
    const stat = bufferStats.find(s => s.category === catId);
    return stat?.count ?? 0;
  }, [bufferStats]);

  // Level badge color
  const getLevelClass = (lvl: string) => {
    switch (lvl) {
      case 'error': return 'logs-tab__level--error';
      case 'warning': return 'logs-tab__level--warning';
      case 'info': return 'logs-tab__level--info';
      case 'perf': return 'logs-tab__level--perf';
      case 'debug': return 'logs-tab__level--debug';
      case 'trace': return 'logs-tab__level--trace';
      default: return '';
    }
  };

  if (!isConnected) {
    return (
      <div className="logs-tab logs-tab--disconnected">
        <p>Connect to server to view logs</p>
      </div>
    );
  }

  return (
    <div className="logs-tab">
      {/* Header with controls */}
      <div className="logs-tab__header">
        {/* Category tabs */}
        <div className="logs-tab__categories">
          {LOG_CATEGORIES.map(({ id, label }) => {
            const count = getCategoryCount(id);
            return (
              <button
                key={id}
                className={`logs-tab__category-btn ${category === id ? 'logs-tab__category-btn--active' : ''}`}
                onClick={() => setCategory(id)}
              >
                {label}
                {count > 0 && (
                  <span className="logs-tab__category-count">{count}</span>
                )}
              </button>
            );
          })}
        </div>

        {/* Level filter and controls */}
        <div className="logs-tab__controls">
          <select
            className="logs-tab__select"
            value={level}
            onChange={(e) => setLevel(e.target.value)}
          >
            {LOG_LEVELS.map(({ id, label }) => (
              <option key={id} value={id}>{label}</option>
            ))}
          </select>

          <label className="logs-tab__auto-refresh">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            Auto
          </label>

          <button
            className="logs-tab__refresh-btn"
            onClick={fetchEntries}
            disabled={isLoading}
            title="Refresh"
          >
            {isLoading ? '...' : '↻'}
          </button>
        </div>
      </div>

      {/* Entries list */}
      <div className="logs-tab__entries" ref={entriesRef}>
        {entries.length === 0 ? (
          <div className="logs-tab__empty">
            {isLoading ? 'Loading...' : 'No entries'}
          </div>
        ) : (
          entries.map((entry) => {
            const isExpanded = expandedEntries.has(entry.seq);
            const hasDetails = entry.details && Object.keys(entry.details).length > 0;

            return (
              <div
                key={entry.seq}
                className={`logs-tab__entry ${isExpanded ? 'logs-tab__entry--expanded' : ''}`}
                onClick={() => hasDetails && toggleEntry(entry.seq)}
              >
                <div className="logs-tab__entry-header">
                  <span className="logs-tab__seq">[{entry.seq}]</span>
                  <span className="logs-tab__timestamp">{entry.timestamp}</span>
                  <span className={`logs-tab__level ${getLevelClass(entry.level)}`}>
                    {entry.level.toUpperCase().slice(0, 3)}
                  </span>
                  <span className="logs-tab__message">{entry.message}</span>
                  {hasDetails && (
                    <span className="logs-tab__expand-hint">
                      {isExpanded ? '▼' : '▶'}
                    </span>
                  )}
                </div>
                {isExpanded && hasDetails && (
                  <pre className="logs-tab__details">
                    {JSON.stringify(entry.details, null, 2)}
                  </pre>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
});

export default LogsTab;
