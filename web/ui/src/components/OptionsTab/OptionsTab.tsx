/**
 * OptionsTab - Configuration panel for app settings
 *
 * Contains cards for:
 * - Logging: Toggle which log categories are written to server-side files
 * - Buffer Stats: Per-category buffer size controls
 * - Server Identity: Git state and server metadata
 */

import React, { useState, useCallback, useEffect, memo } from 'react';
import type { DebugLogServiceClient, TrafficCaptureServiceClient } from '../../../../generated/client';
import type { BufferStats, CaptureStatus, ServerIdentityInfo } from '../../../../generated/types';
import './OptionsTab.css';

// 8 core log categories (matches Category class in Python)
const LOG_CATEGORIES = [
  { id: 'client', label: 'Client', description: 'Web UI events' },
  { id: 'api', label: 'API', description: 'WebSocket, HTTP auth' },
  { id: 'runner', label: 'Runner', description: 'LLM calls, tool execution' },
  { id: 'session', label: 'Session', description: 'Session lifecycle, fork/merge' },
  { id: 'storage', label: 'Storage', description: 'DB reads/writes' },
  { id: 'supervisor', label: 'Supervisor', description: 'Background processes' },
  { id: 'lifecycle', label: 'Lifecycle', description: 'Server start/stop, config' },
  { id: 'perf', label: 'Perf', description: 'Timing markers' },
] as const;

interface OptionsTabProps {
  debugLogClient?: DebugLogServiceClient;
  trafficCaptureClient?: TrafficCaptureServiceClient;
  isConnected: boolean;
}

export const OptionsTab = memo(function OptionsTab({
  debugLogClient,
  trafficCaptureClient,
  isConnected,
}: OptionsTabProps) {
  const [loggingEnabled, setLoggingEnabled] = useState(false);
  const [enabledCategories, setEnabledCategories] = useState<string[]>([]);
  const [bufferStats, setBufferStats] = useState<BufferStats[]>([]);
  const [serverIdentity, setServerIdentity] = useState<ServerIdentityInfo | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [showBufferStats, setShowBufferStats] = useState(false);

  // Load current state on mount
  useEffect(() => {
    if (!debugLogClient || !isConnected) return;

    const loadState = async () => {
      try {
        const [enabled, categories, stats, identity] = await Promise.all([
          debugLogClient.isEnabled(),
          debugLogClient.getCategories(),
          debugLogClient.getBufferStats(),
          debugLogClient.getServerIdentity(),
        ]);
        setLoggingEnabled(enabled);
        setEnabledCategories(categories);
        setBufferStats(stats);
        setServerIdentity(identity);
      } catch (err) {
        console.error('Failed to load debug log state:', err);
      }
    };

    loadState();
  }, [debugLogClient, isConnected]);

  // Refresh buffer stats periodically when panel is showing them
  useEffect(() => {
    if (!debugLogClient || !isConnected || !showBufferStats) return;

    const interval = setInterval(async () => {
      try {
        const stats = await debugLogClient.getBufferStats();
        setBufferStats(stats);
      } catch (err) {
        console.error('Failed to refresh buffer stats:', err);
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [debugLogClient, isConnected, showBufferStats]);

  const handleToggleCategory = useCallback(async (categoryId: string) => {
    if (!debugLogClient) return;

    setIsLoading(true);
    try {
      const isEnabled = enabledCategories.includes(categoryId);
      if (isEnabled) {
        await debugLogClient.disableCategory(categoryId);
        setEnabledCategories(prev => prev.filter(c => c !== categoryId));
      } else {
        await debugLogClient.enableCategory(categoryId);
        setEnabledCategories(prev => [...prev, categoryId]);
      }
    } catch (err) {
      console.error('Failed to toggle category:', err);
    } finally {
      setIsLoading(false);
    }
  }, [debugLogClient, enabledCategories]);

  const handleClearAll = useCallback(async () => {
    if (!debugLogClient) return;

    setIsLoading(true);
    try {
      await debugLogClient.clearCategories();
      setEnabledCategories([]);
    } catch (err) {
      console.error('Failed to clear categories:', err);
    } finally {
      setIsLoading(false);
    }
  }, [debugLogClient]);

  const handleEnableAll = useCallback(async () => {
    if (!debugLogClient) return;

    setIsLoading(true);
    try {
      const allIds = LOG_CATEGORIES.map(c => c.id);
      await debugLogClient.setCategories(allIds);
      setEnabledCategories(allIds);
    } catch (err) {
      console.error('Failed to enable all categories:', err);
    } finally {
      setIsLoading(false);
    }
  }, [debugLogClient]);

  const handleClearBuffer = useCallback(async (category: string | null) => {
    if (!debugLogClient) return;

    try {
      await debugLogClient.clearBuffer(category);
      // Refresh stats
      const stats = await debugLogClient.getBufferStats();
      setBufferStats(stats);
    } catch (err) {
      console.error('Failed to clear buffer:', err);
    }
  }, [debugLogClient]);

  // --- Traffic capture ---
  // Server state is the source of truth: a capture is global and may have been
  // started from another tab or still be running after a page reload.
  const [capture, setCapture] = useState<CaptureStatus | null>(null);
  const [captureLabel, setCaptureLabel] = useState('');
  const [isTogglingCapture, setIsTogglingCapture] = useState(false);

  useEffect(() => {
    if (!trafficCaptureClient || !isConnected) return;

    let cancelled = false;
    const loadStatus = async () => {
      try {
        const status = await trafficCaptureClient.captureStatus();
        if (!cancelled) setCapture(status);
      } catch (err) {
        console.error('Failed to load traffic capture status:', err);
      }
    };

    loadStatus();
    return () => {
      cancelled = true;
    };
  }, [trafficCaptureClient, isConnected]);

  // Refresh counts while a capture is live.
  useEffect(() => {
    if (!trafficCaptureClient || !isConnected || !capture?.active) return;

    const interval = setInterval(async () => {
      try {
        const status = await trafficCaptureClient.captureStatus();
        setCapture(status);
      } catch (err) {
        console.error('Failed to refresh traffic capture status:', err);
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [trafficCaptureClient, isConnected, capture?.active]);

  const handleToggleCapture = useCallback(async () => {
    if (!trafficCaptureClient) return;

    setIsTogglingCapture(true);
    try {
      // start/stop are idempotent server-side, so a double-click or stale
      // toggle state cannot open two captures or error on a redundant stop.
      const status = capture?.active
        ? await trafficCaptureClient.stopCapture()
        : await trafficCaptureClient.startCapture(captureLabel || undefined);
      setCapture(status);
    } catch (err) {
      console.error('Failed to toggle traffic capture:', err);
    } finally {
      setIsTogglingCapture(false);
    }
  }, [trafficCaptureClient, capture?.active, captureLabel]);

  const formatBytes = (bytes: number): string => {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    const exp = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    return `${(bytes / Math.pow(1024, exp)).toFixed(exp === 0 ? 0 : 1)} ${units[exp]}`;
  };

  if (!isConnected) {
    return (
      <div className="options-tab">
        <div className="options-tab__disconnected">
          Connect to server to configure options
        </div>
      </div>
    );
  }

  const hasAnyEnabled = enabledCategories.length > 0;

  const handleToggleLogging = useCallback(async () => {
    if (!debugLogClient) return;

    setIsLoading(true);
    try {
      const newValue = !loggingEnabled;
      await debugLogClient.setEnabled(newValue);
      setLoggingEnabled(newValue);
    } catch (err) {
      console.error('Failed to toggle logging:', err);
    } finally {
      setIsLoading(false);
    }
  }, [debugLogClient, loggingEnabled]);

  // Calculate uptime if we have server identity
  const getUptime = () => {
    if (!serverIdentity?.startTime) return null;
    const start = new Date(serverIdentity.startTime);
    const now = new Date();
    const seconds = Math.floor((now.getTime() - start.getTime()) / 1000);
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
    return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
  };

  // Generate a color from a hex hash (commit or diff hash)
  const hashToColor = (hash: string): string => {
    if (!hash || hash.length < 6) return '#888888';
    // Use first 6 chars as RGB
    const r = parseInt(hash.slice(0, 2), 16);
    const g = parseInt(hash.slice(2, 4), 16);
    const b = parseInt(hash.slice(4, 6), 16);
    // Boost saturation by pushing values away from middle gray
    const boost = (v: number) => {
      const mid = 128;
      const diff = v - mid;
      return Math.max(0, Math.min(255, mid + diff * 1.5));
    };
    return `rgb(${boost(r)}, ${boost(g)}, ${boost(b)})`;
  };

  // Get identity color - use diff hash if dirty, otherwise commit
  const getIdentityColor = () => {
    if (!serverIdentity) return undefined;
    if (serverIdentity.gitDirty && serverIdentity.gitDiffHash) {
      return hashToColor(serverIdentity.gitDiffHash);
    }
    return hashToColor(serverIdentity.gitCommitShort);
  };

  return (
    <div className="options-tab">
      {/* Server Identity Card */}
      {serverIdentity && (
        <div className="options-card options-card--compact">
          <div className="options-card__header">
            <span
              className="server-identity__color"
              style={{ backgroundColor: getIdentityColor() }}
              title={serverIdentity.gitDirty ? `Dirty: ${serverIdentity.gitDiffHash}` : serverIdentity.gitCommitShort}
            />
            <h3 className="options-card__title">Server Identity</h3>
          </div>
          <div className="options-card__content">
            <div className="server-identity">
              <div className="server-identity__row">
                <span className="server-identity__label">Commit</span>
                <span className="server-identity__value">
                  <span
                    className="server-identity__hash-color"
                    style={{ backgroundColor: hashToColor(serverIdentity.gitCommitShort) }}
                  />
                  <code>{serverIdentity.gitCommitShort}</code>
                  {serverIdentity.gitDirty && (
                    <span className="server-identity__dirty">
                      <span
                        className="server-identity__hash-color"
                        style={{ backgroundColor: hashToColor(serverIdentity.gitDiffHash) }}
                      />
                      +{serverIdentity.gitDiffHash}
                    </span>
                  )}
                </span>
              </div>
              <div className="server-identity__row">
                <span className="server-identity__label">Branch</span>
                <span className="server-identity__value">{serverIdentity.gitBranch}</span>
              </div>
              <div className="server-identity__row">
                <span className="server-identity__label">Slot</span>
                <span className="server-identity__value">
                  {serverIdentity.slot} (:{serverIdentity.port})
                </span>
              </div>
              <div className="server-identity__row">
                <span className="server-identity__label">Uptime</span>
                <span className="server-identity__value">{getUptime()}</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Debug Logging Card */}
      <div className="options-card">
        <div className="options-card__header">
          <h3 className="options-card__title">Debug Logging</h3>
        </div>

        <div className="options-card__content">
          {/* Global debug toggle */}
          <label className="debug-toggle">
            <input
              type="checkbox"
              checked={loggingEnabled}
              onChange={handleToggleLogging}
              disabled={isLoading}
            />
            <span className="debug-toggle__label">Enable Debug Logging</span>
            <span className="debug-toggle__description">
              {loggingEnabled ? 'Entries are being collected in buffers' : 'Buffers are frozen (no new entries)'}
            </span>
          </label>

          {/* Category filtering section */}
          <div className={`log-categories-section ${!loggingEnabled ? 'log-categories-section--disabled' : ''}`}>
            <div className="options-card__section-header">
              <span className="options-card__section-title">File Logging Categories</span>
              <span className="options-card__hint">
                {hasAnyEnabled
                  ? `${enabledCategories.length} categor${enabledCategories.length === 1 ? 'y' : 'ies'} → ~/.balloons/logs/`
                  : 'No file logging (memory only)'}
              </span>
            </div>

            <div className="log-categories">
              {LOG_CATEGORIES.map(({ id, label, description }) => {
                const isEnabled = enabledCategories.includes(id);
                const stats = bufferStats.find(s => s.category === id);
                return (
                  <label key={id} className="log-category">
                    <input
                      type="checkbox"
                      checked={isEnabled}
                      onChange={() => handleToggleCategory(id)}
                      disabled={isLoading || !loggingEnabled}
                    />
                    <span className="log-category__label">{label}</span>
                    <span className="log-category__description">{description}</span>
                    {stats && stats.count > 0 && (
                      <span className="log-category__count" title={`${stats.count}/${stats.maxsize} entries`}>
                        {stats.count}
                      </span>
                    )}
                  </label>
                );
              })}
            </div>

            <div className="options-card__actions">
              <button
                className="options-btn options-btn--secondary"
                onClick={handleClearAll}
                disabled={isLoading || !hasAnyEnabled || !loggingEnabled}
                title="Stop writing to any log files"
              >
                Clear Filter
              </button>
              <button
                className="options-btn options-btn--secondary"
                onClick={handleEnableAll}
                disabled={isLoading || !loggingEnabled}
                title="Write all categories to log files"
              >
                Enable All
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Traffic Capture Card */}
      {trafficCaptureClient && (
        <div className="options-card">
          <div className="options-card__header">
            <h3 className="options-card__title">Traffic Capture</h3>
            {capture?.active && (
              <span className="options-card__subtitle">
                {capture.messageCount} frames · {formatBytes(capture.bytesWritten)}
              </span>
            )}
          </div>

          <div className="options-card__content">
            <label className="debug-toggle">
              <input
                type="checkbox"
                checked={capture?.active ?? false}
                onChange={handleToggleCapture}
                disabled={isTogglingCapture}
              />
              <span className="debug-toggle__label">Capture WebSocket Traffic</span>
              <span className="debug-toggle__description">
                {capture?.active
                  ? 'Recording raw frames to disk'
                  : capture?.stopReason && capture.path
                    ? `Last capture ended (${capture.stopReason})`
                    : 'Records every frame to a file for workflow auditing'}
              </span>
            </label>

            <div className={`log-categories-section ${capture?.active ? 'log-categories-section--disabled' : ''}`}>
              <div className="options-card__section-header">
                <span className="options-card__section-title">Workflow Label</span>
                <span className="options-card__hint">Names the capture file</span>
              </div>
              <input
                type="text"
                className="options-input"
                value={captureLabel}
                onChange={e => setCaptureLabel(e.target.value)}
                placeholder="e.g. checkout-flow"
                disabled={capture?.active || isTogglingCapture}
              />
            </div>

            {capture?.path && (
              <div className="server-identity">
                <div className="server-identity__row">
                  <span className="server-identity__label">{capture.active ? 'Writing' : 'File'}</span>
                  <span className="server-identity__value">
                    <code title={capture.path}>{capture.path}</code>
                  </span>
                </div>
              </div>
            )}

            <div className="options-card__hint">
              Format: <code>{'datetime||<client|server>||raw-frame'}</code> — split on the first
              two delimiters only; payloads may contain <code>||</code>.
            </div>
          </div>
        </div>
      )}

      {/* Buffer Stats Card */}
      <div className="options-card">
        <div className="options-card__header">
          <h3 className="options-card__title">Memory Buffers</h3>
          <span className="options-card__subtitle">{loggingEnabled ? 'collecting' : 'frozen'}</span>
          <button
            className="options-btn options-btn--small"
            onClick={() => setShowBufferStats(!showBufferStats)}
          >
            {showBufferStats ? 'Hide' : 'Show'}
          </button>
        </div>

        {showBufferStats && (
          <div className="options-card__content">
            <div className="buffer-stats">
              {bufferStats
                .filter(s => s.count > 0)
                .sort((a, b) => b.count - a.count)
                .map(({ category, count, maxsize }) => (
                  <div key={category} className="buffer-stats__row">
                    <span className="buffer-stats__category">{category}</span>
                    <div className="buffer-stats__bar-container">
                      <div
                        className="buffer-stats__bar"
                        style={{ width: `${(count / maxsize) * 100}%` }}
                      />
                    </div>
                    <span className="buffer-stats__count">{count}/{maxsize}</span>
                    <button
                      className="options-btn options-btn--tiny"
                      onClick={() => handleClearBuffer(category)}
                      title="Clear this buffer"
                    >
                      ×
                    </button>
                  </div>
                ))}
              {bufferStats.filter(s => s.count > 0).length === 0 && (
                <div className="buffer-stats__empty">All buffers empty</div>
              )}
            </div>
            <div className="options-card__actions">
              <button
                className="options-btn options-btn--secondary"
                onClick={() => handleClearBuffer(null)}
                title="Clear all buffers"
              >
                Clear All Buffers
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
});

export default OptionsTab;
