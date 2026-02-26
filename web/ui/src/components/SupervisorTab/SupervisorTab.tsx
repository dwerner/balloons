/**
 * SupervisorTab - Command center for managed hosts, processes, and backends
 *
 * Shows:
 * - Hosts (local and SSH-accessible) with status
 * - Running processes grouped by host
 * - LLM backend status with host mappings
 *
 * Features:
 * - Real-time status updates
 * - Host connectivity checks
 * - Process start/stop controls
 * - Refresh/reload actions
 */

import React, { useState, useCallback, useEffect, memo } from 'react';
import type {
  HostInfo,
  ProcessInfo,
  BackendHostMapping,
  SupervisorState,
} from '../../../../generated/balloons-client';
import { SupervisorStateServiceClient } from '../../../../generated/client';
import './SupervisorTab.css';

// Status indicator component
function StatusIndicator({ status }: { status: string }) {
  const statusConfig: Record<string, { icon: string; className: string; label: string }> = {
    ready: { icon: '🟢', className: 'status--ready', label: 'Ready' },
    reachable: { icon: '🟢', className: 'status--reachable', label: 'Reachable' },
    unreachable: { icon: '🔴', className: 'status--unreachable', label: 'Unreachable' },
    checking: { icon: '🟡', className: 'status--checking', label: 'Checking...' },
    unknown: { icon: '⚪', className: 'status--unknown', label: 'Unknown' },
    error: { icon: '🔴', className: 'status--error', label: 'Error' },
    running: { icon: '🟢', className: 'status--running', label: 'Running' },
    exited: { icon: '⚪', className: 'status--exited', label: 'Exited' },
    failed: { icon: '🔴', className: 'status--failed', label: 'Failed' },
  };

  const fallback = { icon: '⚪', className: 'status--unknown', label: 'Unknown' };
  const config = statusConfig[status || 'unknown'] || fallback;

  return (
    <span className={`supervisor-status ${config.className}`} title={config.label}>
      {config.icon}
    </span>
  );
}

// Action button component
function ActionButton({
  label,
  onClick,
  disabled = false,
  variant = 'default',
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  variant?: 'default' | 'primary' | 'danger';
}) {
  return (
    <button
      className={`supervisor-action supervisor-action--${variant}`}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      disabled={disabled}
    >
      {label}
    </button>
  );
}

// Host card component
const HostCard = memo(function HostCard({
  host,
  processCount,
  onCheckStatus,
  isChecking,
}: {
  host: HostInfo;
  processCount: number;
  onCheckStatus: (hostName: string) => void;
  isChecking: boolean;
}) {
  const displayStatus = isChecking ? 'checking' : (host.status || 'unknown');

  return (
    <div className="supervisor-host-card">
      <div className="supervisor-host-card__header">
        <StatusIndicator status={displayStatus} />
        <span className="supervisor-host-card__name">{host.name}</span>
        {host.type === 'ssh' && (
          <span className="supervisor-host-card__address">
            {host.user}@{host.host}
            {host.port && host.port !== 22 && `:${host.port}`}
          </span>
        )}
        {host.type === 'local' && (
          <span className="supervisor-host-card__address">this machine</span>
        )}
      </div>

      {host.tags && host.tags.length > 0 && (
        <div className="supervisor-host-card__tags">
          {host.tags.map((tag) => (
            <span key={tag} className="supervisor-tag">
              {tag}
            </span>
          ))}
        </div>
      )}

      <div className="supervisor-host-card__footer">
        {processCount > 0 && (
          <span className="supervisor-host-card__processes">
            {processCount} process{processCount !== 1 ? 'es' : ''}
          </span>
        )}
        {host.latencyMs !== undefined && host.latencyMs !== null && (
          <span className="supervisor-host-card__latency">{host.latencyMs}ms</span>
        )}
        {host.type === 'ssh' && (
          <ActionButton
            label={isChecking ? '...' : 'Check'}
            onClick={() => onCheckStatus(host.name)}
            disabled={isChecking}
          />
        )}
      </div>

      {host.error && (
        <div className="supervisor-host-card__error-block">
          <pre>{host.error}</pre>
        </div>
      )}
    </div>
  );
});

// Process card component
const ProcessCard = memo(function ProcessCard({
  process,
  onViewLogs,
  onStop,
}: {
  process: ProcessInfo;
  onViewLogs: (processId: string) => void;
  onStop: (processId: string) => void;
}) {
  // Format runtime
  const formatRuntime = (seconds: number | null | undefined): string => {
    if (!seconds) return '';
    if (seconds < 60) return `${Math.floor(seconds)}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
    return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
  };

  return (
    <div className="supervisor-process-card">
      <div className="supervisor-process-card__header">
        <StatusIndicator status={process.status} />
        <span className="supervisor-process-card__name">
          {process.name || process.processId.slice(0, 8)}
        </span>
        {process.runtimeSeconds && (
          <span className="supervisor-process-card__runtime">
            {formatRuntime(process.runtimeSeconds)}
          </span>
        )}
      </div>

      <div className="supervisor-process-card__command">
        <code>{process.command}</code>
      </div>

      <div className="supervisor-process-card__footer">
        <span className="supervisor-process-card__session">
          Session: {process.sessionId.slice(0, 8)}
        </span>
        <div className="supervisor-process-card__actions">
          <ActionButton label="Logs" onClick={() => onViewLogs(process.processId)} />
          {process.status === 'running' && (
            <ActionButton
              label="Stop"
              onClick={() => onStop(process.processId)}
              variant="danger"
            />
          )}
        </div>
      </div>
    </div>
  );
});

// Backend card component
const BackendCard = memo(function BackendCard({
  backend,
  hostName,
  hostStatus,
}: {
  backend: string;
  hostName: string | null;
  hostStatus: string;
}) {
  return (
    <div className="supervisor-backend-card">
      <span className="supervisor-backend-card__name">{backend}</span>
      {hostName ? (
        <>
          <StatusIndicator status={hostStatus} />
          <span className="supervisor-backend-card__host">{hostName}</span>
        </>
      ) : (
        <span className="supervisor-backend-card__host">configured</span>
      )}
    </div>
  );
});

// Section header component
function SectionHeader({
  icon,
  title,
  count,
  action,
}: {
  icon: string;
  title: string;
  count?: number;
  action?: React.ReactNode;
}) {
  return (
    <div className="supervisor-section__header">
      <span className="supervisor-section__icon">{icon}</span>
      <span className="supervisor-section__title">{title}</span>
      {count !== undefined && (
        <span className="supervisor-section__count">({count})</span>
      )}
      {action && <div className="supervisor-section__action">{action}</div>}
    </div>
  );
}

// Main component props
export interface SupervisorTabProps {
  /** Supervisor service client */
  supervisorClient?: SupervisorStateServiceClient;
  /** Whether loading */
  isLoading?: boolean;
  /** Callback when process logs requested */
  onViewLogs?: (processId: string) => void;
  /** Callback when process stop requested */
  onStopProcess?: (processId: string) => void;
}

export function SupervisorTab({
  supervisorClient,
  isLoading = false,
  onViewLogs,
  onStopProcess,
}: SupervisorTabProps) {
  const [state, setState] = useState<SupervisorState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checkingHosts, setCheckingHosts] = useState<Set<string>>(new Set());
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Load initial state
  const loadState = useCallback(async () => {
    if (!supervisorClient) return;

    try {
      setIsRefreshing(true);
      const newState = await supervisorClient.getState();
      setState(newState);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load supervisor state');
    } finally {
      setIsRefreshing(false);
    }
  }, [supervisorClient]);

  // Initial load
  useEffect(() => {
    loadState();
  }, [loadState]);

  // Subscribe to events
  useEffect(() => {
    if (!supervisorClient) return;

    const unsubs: Array<() => void> = [];

    // Subscribe to state updates
    unsubs.push(
      supervisorClient.supervisorStateUpdated((newState) => {
        setState(newState);
      })
    );

    // Subscribe to host status changes
    unsubs.push(
      supervisorClient.hostStatusChanged((host) => {
        setState((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            hosts: prev.hosts.map((h) => (h.name === host.name ? host : h)),
          };
        });
        setCheckingHosts((prev) => {
          const next = new Set(prev);
          next.delete(host.name);
          return next;
        });
      })
    );

    // Subscribe to process events
    unsubs.push(
      supervisorClient.processStarted((process) => {
        setState((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            processes: [...prev.processes, process],
          };
        });
      })
    );

    unsubs.push(
      supervisorClient.processStopped((process) => {
        setState((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            processes: prev.processes.map((p) =>
              p.processId === process.processId ? process : p
            ),
          };
        });
      })
    );

    return () => {
      unsubs.forEach((unsub) => unsub());
    };
  }, [supervisorClient]);

  // Check host status
  const handleCheckHostStatus = useCallback(
    async (hostName: string) => {
      if (!supervisorClient) return;

      setCheckingHosts((prev) => new Set(prev).add(hostName));

      try {
        const result = await supervisorClient.checkHostStatus(hostName);
        // Update the host in state
        setState((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            hosts: prev.hosts.map((h) =>
              h.name === hostName
                ? {
                    ...h,
                    status: result.status,
                    latencyMs: result.latencyMs ?? undefined,
                    error: result.error ?? undefined,
                  }
                : h
            ),
          };
        });
      } catch (e) {
        console.error('Failed to check host status:', e);
      } finally {
        setCheckingHosts((prev) => {
          const next = new Set(prev);
          next.delete(hostName);
          return next;
        });
      }
    },
    [supervisorClient]
  );

  // View process logs
  const handleViewLogs = useCallback(
    (processId: string) => {
      if (onViewLogs) {
        onViewLogs(processId);
      } else {
        console.log('View logs for process:', processId);
      }
    },
    [onViewLogs]
  );

  // Stop process
  const handleStopProcess = useCallback(
    (processId: string) => {
      if (onStopProcess) {
        onStopProcess(processId);
      } else {
        console.log('Stop process:', processId);
      }
    },
    [onStopProcess]
  );

  // Group processes by host
  const processesByHost = React.useMemo(() => {
    if (!state?.processes) return new Map<string, ProcessInfo[]>();

    const grouped = new Map<string, ProcessInfo[]>();
    for (const process of state.processes) {
      const host = process.host || 'local';
      if (!grouped.has(host)) {
        grouped.set(host, []);
      }
      grouped.get(host)!.push(process);
    }
    return grouped;
  }, [state?.processes]);

  // Get host status for backend
  const getHostStatusForBackend = (hostName: string): string => {
    const host = state?.hosts.find((h) => h.name === hostName);
    return host?.status || 'unknown';
  };

  // Loading state
  if (isLoading || (!state && !error)) {
    return (
      <div className="supervisor-tab supervisor-tab--loading">
        <div className="supervisor-loading">Loading supervisor state...</div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="supervisor-tab supervisor-tab--error">
        <div className="supervisor-error">
          <span className="supervisor-error__icon">⚠️</span>
          <span className="supervisor-error__message">{error}</span>
          <ActionButton label="Retry" onClick={loadState} variant="primary" />
        </div>
      </div>
    );
  }

  const runningCount = state?.processes.filter((p) => p.status === 'running').length || 0;

  return (
    <div className="supervisor-tab">
      {/* Header */}
      <div className="supervisor-tab__header">
        <h2>Supervisor</h2>
        <ActionButton
          label={isRefreshing ? 'Refreshing...' : 'Refresh'}
          onClick={loadState}
          disabled={isRefreshing}
        />
      </div>

      {/* Hosts Section */}
      <section className="supervisor-section">
        <SectionHeader
          icon="🖥️"
          title="HOSTS"
          count={state?.hosts.length}
        />
        <div className="supervisor-hosts-grid">
          {state?.hosts.map((host) => (
            <HostCard
              key={host.name}
              host={host}
              processCount={processesByHost.get(host.name)?.length || 0}
              onCheckStatus={handleCheckHostStatus}
              isChecking={checkingHosts.has(host.name)}
            />
          ))}
        </div>
      </section>

      {/* Processes Section */}
      <section className="supervisor-section">
        <SectionHeader
          icon="⚙️"
          title="PROCESSES"
          count={state?.processes.length}
          action={
            runningCount > 0 && (
              <span className="supervisor-running-count">
                {runningCount} running
              </span>
            )
          }
        />
        {state?.processes.length === 0 ? (
          <div className="supervisor-empty">No supervised processes</div>
        ) : (
          <div className="supervisor-processes">
            {Array.from(processesByHost.entries()).map(([hostName, processes]) => (
              <div key={hostName} className="supervisor-host-processes">
                <div className="supervisor-host-processes__header">
                  {hostName} ({processes.length})
                </div>
                <div className="supervisor-processes-list">
                  {processes.map((process) => (
                    <ProcessCard
                      key={process.processId}
                      process={process}
                      onViewLogs={handleViewLogs}
                      onStop={handleStopProcess}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Backends Section */}
      {state?.backendHosts && state.backendHosts.length > 0 && (
        <section className="supervisor-section">
          <SectionHeader
            icon="📡"
            title="LLM BACKENDS"
            count={state.backendHosts.length}
          />
          <div className="supervisor-backends-list">
            {state.backendHosts.map((mapping) => (
              <BackendCard
                key={mapping.backendName}
                backend={mapping.backendName}
                hostName={mapping.hostName}
                hostStatus={getHostStatusForBackend(mapping.hostName)}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

export default SupervisorTab;
