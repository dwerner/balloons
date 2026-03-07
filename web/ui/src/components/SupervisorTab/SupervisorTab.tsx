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
 *
 * URL ROUTING INTEGRATION:
 * - Process selection should update URL to #/supervisor/:processId
 * - Host selection could use #/supervisor/host/:hostName
 * - See docs/url-routing.md for the full routing design
 */

import React, { useState, useCallback, useEffect, memo } from 'react';
import type {
  HostInfo,
  ProcessInfo,
  BackendHostMapping,
  SupervisorState,
  HostUpdateRequest,
} from '../../../../generated/balloons-client';
import { SupervisorStateServiceClient, LSPServiceClient } from '../../../../generated/client';
import { useDialog } from '../Dialog';
import { ProcessLogViewer } from './ProcessLogViewer';
import { LSPSection } from './LSPSection';
import './SupervisorTab.css';

// Form state for host editing
interface HostFormState {
  name: string;
  type: 'local' | 'ssh';
  host: string;
  user: string;
  port: number;
  tags: string;
  description: string;
}

const emptyHostForm: HostFormState = {
  name: '',
  type: 'ssh',
  host: '',
  user: '',
  port: 22,
  tags: '',
  description: '',
};

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
  onEdit,
  onDelete,
  isChecking,
}: {
  host: HostInfo;
  processCount: number;
  onCheckStatus: (hostName: string) => void;
  onEdit: (host: HostInfo) => void;
  onDelete: (hostName: string) => void;
  isChecking: boolean;
}) {
  const displayStatus = isChecking ? 'checking' : (host.status || 'unknown');
  const isLocal = host.name === 'local';

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
          <span className="supervisor-host-card__address">{host.host || 'this machine'}</span>
        )}
        <div className="supervisor-host-card__edit-actions">
          <ActionButton
            label="✎"
            onClick={() => onEdit(host)}
          />
          {!isLocal && (
            <ActionButton
              label="×"
              onClick={() => onDelete(host.name)}
              variant="danger"
            />
          )}
        </div>
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
  onRemove,
}: {
  backend: string;
  hostName: string | null;
  hostStatus: string;
  onRemove?: (backendName: string) => void;
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
      {onRemove && (
        <ActionButton
          label="×"
          onClick={() => onRemove(backend)}
          variant="danger"
        />
      )}
    </div>
  );
});

// Host edit modal
function HostEditModal({
  isOpen,
  onClose,
  onSave,
  initialData,
  isNew,
  isSaving,
  error,
}: {
  isOpen: boolean;
  onClose: () => void;
  onSave: (data: HostFormState) => void;
  initialData: HostFormState;
  isNew: boolean;
  isSaving: boolean;
  error: string | null;
}) {
  const [form, setForm] = useState<HostFormState>(initialData);

  useEffect(() => {
    setForm(initialData);
  }, [initialData]);

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave(form);
  };

  const updateField = <K extends keyof HostFormState>(
    field: K,
    value: HostFormState[K]
  ) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  return (
    <div className="supervisor-modal-overlay" onClick={onClose}>
      <div className="supervisor-modal" onClick={(e) => e.stopPropagation()}>
        <div className="supervisor-modal__header">
          <h3>{isNew ? 'Add Host' : `Edit Host: ${initialData.name}`}</h3>
          <button className="supervisor-modal__close" onClick={onClose}>
            ×
          </button>
        </div>

        <form onSubmit={handleSubmit} className="supervisor-modal__form">
          <div className="supervisor-form-field">
            <label htmlFor="host-name">Name</label>
            <input
              id="host-name"
              type="text"
              value={form.name}
              onChange={(e) => updateField('name', e.target.value)}
              placeholder="my-server"
              required
              disabled={isSaving || form.name === 'local'}
            />
            {!isNew && form.name === 'local' && (
              <span className="supervisor-form-field__hint">Cannot rename local host</span>
            )}
          </div>

          <div className="supervisor-form-field">
            <label htmlFor="host-type">Type</label>
            <select
              id="host-type"
              value={form.type}
              onChange={(e) => updateField('type', e.target.value as 'local' | 'ssh')}
              disabled={isSaving || form.name === 'local'}
            >
              <option value="ssh">SSH</option>
              <option value="local">Local</option>
            </select>
          </div>

          {form.type === 'ssh' && (
            <>
              <div className="supervisor-form-field">
                <label htmlFor="host-host">Host / IP</label>
                <input
                  id="host-host"
                  type="text"
                  value={form.host}
                  onChange={(e) => updateField('host', e.target.value)}
                  placeholder="192.168.1.100"
                  required={form.type === 'ssh'}
                  disabled={isSaving}
                />
              </div>

              <div className="supervisor-form-field">
                <label htmlFor="host-user">User</label>
                <input
                  id="host-user"
                  type="text"
                  value={form.user}
                  onChange={(e) => updateField('user', e.target.value)}
                  placeholder="deploy"
                  required={form.type === 'ssh'}
                  disabled={isSaving}
                />
              </div>

              <div className="supervisor-form-field">
                <label htmlFor="host-port">Port</label>
                <input
                  id="host-port"
                  type="number"
                  value={form.port}
                  onChange={(e) => updateField('port', parseInt(e.target.value) || 22)}
                  min={1}
                  max={65535}
                  disabled={isSaving}
                />
              </div>

              <div className="supervisor-form-field__tip">
                <p>To copy your SSH key for passwordless login:</p>
                <div className="supervisor-form-field__tip-command">
                  <code>ssh-copy-id {form.user || 'user'}@{form.host || 'host'}{form.port && form.port !== 22 ? ` -p ${form.port}` : ''}</code>
                  <button
                    type="button"
                    className="supervisor-form-field__tip-copy"
                    onClick={() => {
                      const cmd = `ssh-copy-id ${form.user || 'user'}@${form.host || 'host'}${form.port && form.port !== 22 ? ` -p ${form.port}` : ''}`;
                      navigator.clipboard.writeText(cmd);
                    }}
                    title="Copy to clipboard"
                  >
                    📋
                  </button>
                </div>
              </div>
            </>
          )}

          <div className="supervisor-form-field">
            <label htmlFor="host-tags">Tags (comma-separated)</label>
            <input
              id="host-tags"
              type="text"
              value={form.tags}
              onChange={(e) => updateField('tags', e.target.value)}
              placeholder="docker, ml, web"
              disabled={isSaving}
            />
          </div>

          <div className="supervisor-form-field">
            <label htmlFor="host-description">Description</label>
            <input
              id="host-description"
              type="text"
              value={form.description}
              onChange={(e) => updateField('description', e.target.value)}
              placeholder="Production web server"
              disabled={isSaving}
            />
          </div>

          {error && (
            <div className="supervisor-form-error">
              <pre>{error}</pre>
            </div>
          )}

          <div className="supervisor-modal__actions">
            <ActionButton
              label="Cancel"
              onClick={onClose}
              disabled={isSaving}
            />
            <button
              type="submit"
              className="supervisor-action supervisor-action--primary"
              disabled={isSaving}
            >
              {isSaving ? 'Saving...' : isNew ? 'Add Host' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

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
  /** LSP service client */
  lspClient?: LSPServiceClient;
  /** Whether loading */
  isLoading?: boolean;
  /** Callback when process logs requested */
  onViewLogs?: (processId: string) => void;
  /** Callback when process stop requested */
  onStopProcess?: (processId: string) => void;
}

export function SupervisorTab({
  supervisorClient,
  lspClient,
  isLoading = false,
  onViewLogs,
  onStopProcess,
}: SupervisorTabProps) {
  const { confirm, alert } = useDialog();
  const [state, setState] = useState<SupervisorState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checkingHosts, setCheckingHosts] = useState<Set<string>>(new Set());
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Process log viewer state
  const [viewingProcess, setViewingProcess] = useState<ProcessInfo | null>(null);

  // LSP section collapse state
  const [lspCollapsed, setLspCollapsed] = useState(false);

  // Host edit modal state
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingHost, setEditingHost] = useState<HostFormState>(emptyHostForm);
  const [isNewHost, setIsNewHost] = useState(true);
  const [originalHostName, setOriginalHostName] = useState<string | null>(null); // Track original name for renames
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

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
      // Find the process in state
      const process = state?.processes.find((p) => p.processId === processId);
      if (process) {
        setViewingProcess(process);
      }
      // Also call external handler if provided
      if (onViewLogs) {
        onViewLogs(processId);
      }
    },
    [onViewLogs, state?.processes]
  );

  // Close log viewer
  const handleCloseLogViewer = useCallback(() => {
    setViewingProcess(null);
  }, []);

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

  // Open add host modal
  const handleAddHost = useCallback(() => {
    setEditingHost(emptyHostForm);
    setIsNewHost(true);
    setOriginalHostName(null);
    setSaveError(null);
    setEditModalOpen(true);
  }, []);

  // Open edit host modal
  const handleEditHost = useCallback((host: HostInfo) => {
    setEditingHost({
      name: host.name,
      type: host.type as 'local' | 'ssh',
      host: host.host || '',
      user: host.user || '',
      port: host.port ?? 22,
      tags: (host.tags || []).join(', '),
      description: host.description || '',
    });
    setIsNewHost(false);
    setOriginalHostName(host.name); // Track original name for potential rename
    setSaveError(null);
    setEditModalOpen(true);
  }, []);

  // Save host
  const handleSaveHost = useCallback(
    async (form: HostFormState) => {
      if (!supervisorClient) return;

      setIsSaving(true);
      setSaveError(null);

      try {
        const request: HostUpdateRequest = {
          name: form.name,
          type: form.type,
          host: form.type === 'ssh' ? form.host : undefined,
          user: form.type === 'ssh' ? form.user : undefined,
          port: form.port,
          tags: form.tags
            .split(',')
            .map((t) => t.trim())
            .filter((t) => t.length > 0),
          description: form.description || undefined,
          // Pass originalName for rename support (only when editing and name changed)
          originalName: !isNewHost && originalHostName && originalHostName !== form.name
            ? originalHostName
            : undefined,
        };

        const result = isNewHost
          ? await supervisorClient.addHost(request)
          : await supervisorClient.updateHost(request);

        if (!result.success) {
          setSaveError(result.error || 'Unknown error');
          return;
        }

        // Success - close modal and reload
        setEditModalOpen(false);
        loadState();
      } catch (e) {
        setSaveError(e instanceof Error ? e.message : 'Failed to save host');
      } finally {
        setIsSaving(false);
      }
    },
    [supervisorClient, isNewHost, originalHostName, loadState]
  );

  // Delete host
  const handleDeleteHost = useCallback(
    async (hostName: string) => {
      if (!supervisorClient) return;
      const confirmed = await confirm({
        title: 'Delete Host',
        message: `Delete host "${hostName}"?`,
        confirmText: 'Delete',
        variant: 'danger',
      });
      if (!confirmed) return;

      try {
        const result = await supervisorClient.removeHost(hostName);
        if (!result.success) {
          await alert({
            title: 'Error',
            message: result.error || 'Failed to delete host',
          });
          return;
        }
        loadState();
      } catch (e) {
        await alert({
          title: 'Error',
          message: e instanceof Error ? e.message : 'Failed to delete host',
        });
      }
    },
    [supervisorClient, loadState, confirm, alert]
  );

  // Remove backend mapping
  const handleRemoveBackendHost = useCallback(
    async (backendName: string) => {
      if (!supervisorClient) return;
      const confirmed = await confirm({
        title: 'Remove Backend Mapping',
        message: `Remove backend mapping for "${backendName}"?`,
        confirmText: 'Remove',
        variant: 'warning',
      });
      if (!confirmed) return;

      try {
        const result = await supervisorClient.removeBackendHost(backendName);
        if (!result.success) {
          await alert({
            title: 'Error',
            message: result.error || 'Failed to remove backend mapping',
          });
          return;
        }
        loadState();
      } catch (e) {
        await alert({
          title: 'Error',
          message: e instanceof Error ? e.message : 'Failed to remove backend mapping',
        });
      }
    },
    [supervisorClient, loadState, confirm, alert]
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
      </div>

      {/* Host Edit Modal */}
      <HostEditModal
        isOpen={editModalOpen}
        onClose={() => setEditModalOpen(false)}
        onSave={handleSaveHost}
        initialData={editingHost}
        isNew={isNewHost}
        isSaving={isSaving}
        error={saveError}
      />

      {/* Hosts Section */}
      <section className="supervisor-section">
        <SectionHeader
          icon="🖥️"
          title="HOSTS"
          count={state?.hosts.length}
          action={
            <ActionButton
              label="+ Add Host"
              onClick={handleAddHost}
              variant="primary"
            />
          }
        />
        <div className="supervisor-hosts-grid">
          {state?.hosts.map((host) => (
            <HostCard
              key={host.name}
              host={host}
              processCount={processesByHost.get(host.name)?.length || 0}
              onCheckStatus={handleCheckHostStatus}
              onEdit={handleEditHost}
              onDelete={handleDeleteHost}
              isChecking={checkingHosts.has(host.name)}
            />
          ))}
        </div>
      </section>

      {/* LSP Servers Section */}
      <LSPSection
        lspClient={lspClient}
        supervisorClient={supervisorClient}
        isCollapsed={lspCollapsed}
        onToggleCollapse={() => setLspCollapsed(!lspCollapsed)}
      />

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
                onRemove={handleRemoveBackendHost}
              />
            ))}
          </div>
        </section>
      )}

      {/* Process Log Viewer */}
      {viewingProcess && supervisorClient && (
        <div className="supervisor-modal-overlay" onClick={handleCloseLogViewer}>
          <div className="supervisor-modal supervisor-modal--logs" onClick={(e) => e.stopPropagation()}>
            <ProcessLogViewer
              process={viewingProcess}
              client={supervisorClient}
              onClose={handleCloseLogViewer}
            />
          </div>
        </div>
      )}
    </div>
  );
}

export default SupervisorTab;
