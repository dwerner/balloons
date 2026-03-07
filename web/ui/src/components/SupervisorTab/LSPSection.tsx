/**
 * LSPSection - Language Server Process Management
 *
 * A collapsible section within SupervisorTab that shows:
 * - Configured language servers (from supervisor.yaml)
 * - Running LSP server instances with status
 * - Start/stop/restart controls
 *
 * Uses the LSPService WebSocket API for real-time updates.
 */

import React, { useState, useCallback, useEffect, memo } from 'react';
import type {
  LSPServerConfig,
  LSPServerInstance,
  LSPStatusResult,
  ProcessInfo,
} from '../../../../generated/balloons-client';
import type { LSPServiceClient, SupervisorStateServiceClient } from '../../../../generated/client';
import { useDialog } from '../Dialog';
import { ProcessLogViewer } from './ProcessLogViewer';

// Language icons mapping
const LANGUAGE_ICONS: Record<string, string> = {
  python: '\u{1F40D}',      // snake
  typescript: '\u{1F4DC}',  // scroll
  javascript: '\u{1F4DC}',  // scroll
  rust: '\u{2699}\uFE0F',   // gear
  go: '\u{1F439}',          // hamster (gopher-ish)
  java: '\u{2615}',         // coffee
  default: '\u{1F4BB}',     // laptop
};

function getLanguageIcon(language: string): string {
  const icon = LANGUAGE_ICONS[language.toLowerCase()];
  return icon ?? LANGUAGE_ICONS['default'] ?? '\u{1F4BB}';
}

// Format idle time for display
function formatIdleTime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

// Format timeout for display
function formatTimeout(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h`;
}

// Status indicator component (reuse pattern from SupervisorTab)
function StatusIndicator({ status }: { status: string }) {
  const statusConfig: Record<string, { icon: string; className: string; label: string }> = {
    running: { icon: '\u{1F7E2}', className: 'status--running', label: 'Running' },
    initializing: { icon: '\u{1F7E1}', className: 'status--checking', label: 'Initializing' },
    exited: { icon: '\u{26AA}', className: 'status--exited', label: 'Exited' },
    failed: { icon: '\u{1F534}', className: 'status--failed', label: 'Failed' },
    unknown: { icon: '\u{26AA}', className: 'status--unknown', label: 'Unknown' },
  };

  const fallback = { icon: '\u{26AA}', className: 'status--unknown', label: 'Unknown' };
  const config = statusConfig[status || 'unknown'] || fallback;

  return (
    <span className={`supervisor-status ${config.className}`} title={config.label}>
      {config.icon}
    </span>
  );
}

// Action button component (reuse pattern from SupervisorTab)
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

// Instance card - shows a running LSP server instance
interface LSPInstanceCardProps {
  instance: LSPServerInstance;
  onViewLogs: (instance: LSPServerInstance) => void;
  onRestart: (key: string) => void;
  onStop: (key: string) => void;
  isRestarting: boolean;
  isStopping: boolean;
}

const LSPInstanceCard = memo(function LSPInstanceCard({
  instance,
  onViewLogs,
  onRestart,
  onStop,
  isRestarting,
  isStopping,
}: LSPInstanceCardProps) {
  const status = instance.initialized ? instance.processStatus : 'initializing';
  const isRunning = status === 'running';

  // Truncate workspace path for display
  const displayWorkspace = instance.workspace.length > 40
    ? '...' + instance.workspace.slice(-37)
    : instance.workspace;

  return (
    <div className="lsp-instance-card">
      <div className="lsp-instance-card__header">
        <StatusIndicator status={status} />
        <span className="lsp-instance-card__workspace" title={instance.workspace}>
          {displayWorkspace}
        </span>
      </div>

      <div className="lsp-instance-card__stats">
        <span className="lsp-instance-card__stat">
          idle: {formatIdleTime(instance.idleSeconds)}
        </span>
        {instance.pendingRequests > 0 && (
          <span className="lsp-instance-card__stat lsp-instance-card__stat--pending">
            reqs: {instance.pendingRequests}
          </span>
        )}
        {!instance.initialized && (
          <span className="lsp-instance-card__stat lsp-instance-card__stat--init">
            initializing...
          </span>
        )}
      </div>

      <div className="lsp-instance-card__actions">
        <ActionButton
          label="Logs"
          onClick={() => onViewLogs(instance)}
        />
        <ActionButton
          label={isRestarting ? '...' : 'Restart'}
          onClick={() => onRestart(instance.key)}
          disabled={isRestarting || isStopping}
        />
        {isRunning && (
          <ActionButton
            label={isStopping ? '...' : 'Stop'}
            onClick={() => onStop(instance.key)}
            disabled={isRestarting || isStopping}
            variant="danger"
          />
        )}
      </div>
    </div>
  );
});

// Server config card - shows a configured server with its instances
interface LSPServerConfigCardProps {
  config: LSPServerConfig;
  instances: LSPServerInstance[];
  onStart: (language: string) => void;
  onViewLogs: (instance: LSPServerInstance) => void;
  onRestart: (key: string) => void;
  onStop: (key: string) => void;
  restartingKeys: Set<string>;
  stoppingKeys: Set<string>;
  isStarting: boolean;
}

const LSPServerConfigCard = memo(function LSPServerConfigCard({
  config,
  instances,
  onStart,
  onViewLogs,
  onRestart,
  onStop,
  restartingKeys,
  stoppingKeys,
  isStarting,
}: LSPServerConfigCardProps) {
  const icon = getLanguageIcon(config.name);
  const hasInstances = instances.length > 0;

  return (
    <div className="lsp-server-card">
      <div className="lsp-server-card__header">
        <span className="lsp-server-card__icon">{icon}</span>
        <span className="lsp-server-card__name">{config.name}</span>
        {hasInstances && (
          <span className="lsp-server-card__count">
            {instances.length} running
          </span>
        )}
      </div>

      <div className="lsp-server-card__details">
        <div className="lsp-server-card__command">
          <code>{config.command}</code>
        </div>
        <div className="lsp-server-card__meta">
          <span className="lsp-server-card__extensions">
            {config.extensions.join(', ')}
          </span>
          <span className="lsp-server-card__timeout">
            timeout: {formatTimeout(config.idleTimeoutSeconds)}
          </span>
        </div>
      </div>

      {hasInstances && (
        <div className="lsp-server-card__instances">
          <div className="lsp-server-card__instances-header">Instances:</div>
          {instances.map((instance) => (
            <LSPInstanceCard
              key={instance.key}
              instance={instance}
              onViewLogs={onViewLogs}
              onRestart={onRestart}
              onStop={onStop}
              isRestarting={restartingKeys.has(instance.key)}
              isStopping={stoppingKeys.has(instance.key)}
            />
          ))}
        </div>
      )}

      <div className="lsp-server-card__footer">
        <ActionButton
          label={isStarting ? 'Starting...' : 'Start for CWD'}
          onClick={() => onStart(config.name)}
          disabled={isStarting}
          variant="primary"
        />
      </div>
    </div>
  );
});

// Main section component
export interface LSPSectionProps {
  lspClient?: LSPServiceClient;
  supervisorClient?: SupervisorStateServiceClient;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
}

export function LSPSection({
  lspClient,
  supervisorClient,
  isCollapsed = false,
  onToggleCollapse,
}: LSPSectionProps) {
  const { confirm, alert } = useDialog();

  // State
  const [status, setStatus] = useState<LSPStatusResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [startingServers, setStartingServers] = useState<Set<string>>(new Set());
  const [restartingKeys, setRestartingKeys] = useState<Set<string>>(new Set());
  const [stoppingKeys, setStoppingKeys] = useState<Set<string>>(new Set());

  // Log viewer state
  const [viewingLogsInstance, setViewingLogsInstance] = useState<LSPServerInstance | null>(null);

  // Load initial status
  const loadStatus = useCallback(async () => {
    if (!lspClient) return;

    try {
      setIsLoading(true);
      const result = await lspClient.getStatus();
      setStatus(result);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load LSP status');
    } finally {
      setIsLoading(false);
    }
  }, [lspClient]);

  // Initial load
  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  // Subscribe to events
  useEffect(() => {
    if (!lspClient) return;

    const unsubs: Array<() => void> = [];

    // On server started - reload status
    unsubs.push(
      lspClient.lspServerStarted(() => {
        loadStatus();
      })
    );

    // On server stopped - reload status
    unsubs.push(
      lspClient.lspServerStopped(() => {
        loadStatus();
      })
    );

    // On server restarted - reload status
    unsubs.push(
      lspClient.lspServerRestarted(() => {
        loadStatus();
      })
    );

    return () => {
      unsubs.forEach((unsub) => unsub());
    };
  }, [lspClient, loadStatus]);

  // Start server for current working directory
  const handleStart = useCallback(
    async (language: string) => {
      if (!lspClient) return;

      setStartingServers((prev) => new Set(prev).add(language));

      try {
        const result = await lspClient.startServer(language);
        if (!result.success) {
          await alert({
            title: 'Failed to Start Server',
            message: result.error || 'Unknown error',
          });
        }
        // Reload to get updated status
        loadStatus();
      } catch (e) {
        await alert({
          title: 'Error',
          message: e instanceof Error ? e.message : 'Failed to start server',
        });
      } finally {
        setStartingServers((prev) => {
          const next = new Set(prev);
          next.delete(language);
          return next;
        });
      }
    },
    [lspClient, loadStatus, alert]
  );

  // Restart server instance
  const handleRestart = useCallback(
    async (key: string) => {
      if (!lspClient) return;

      setRestartingKeys((prev) => new Set(prev).add(key));

      try {
        const result = await lspClient.restartServer(null, null, key);
        if (!result.success) {
          await alert({
            title: 'Failed to Restart Server',
            message: result.error || 'Unknown error',
          });
        }
        loadStatus();
      } catch (e) {
        await alert({
          title: 'Error',
          message: e instanceof Error ? e.message : 'Failed to restart server',
        });
      } finally {
        setRestartingKeys((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
      }
    },
    [lspClient, loadStatus, alert]
  );

  // Stop server instance
  const handleStop = useCallback(
    async (key: string) => {
      if (!lspClient) return;

      setStoppingKeys((prev) => new Set(prev).add(key));

      try {
        const result = await lspClient.stopServer(null, null, key);
        if (!result.success) {
          await alert({
            title: 'Failed to Stop Server',
            message: result.error || 'Unknown error',
          });
        }
        loadStatus();
      } catch (e) {
        await alert({
          title: 'Error',
          message: e instanceof Error ? e.message : 'Failed to stop server',
        });
      } finally {
        setStoppingKeys((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
      }
    },
    [lspClient, loadStatus, alert]
  );

  // View logs for an LSP server instance
  const handleViewLogs = useCallback((instance: LSPServerInstance) => {
    setViewingLogsInstance(instance);
  }, []);

  // Close log viewer
  const handleCloseLogViewer = useCallback(() => {
    setViewingLogsInstance(null);
  }, []);

  // Stop all servers
  const handleStopAll = useCallback(async () => {
    if (!lspClient) return;

    const confirmed = await confirm({
      title: 'Stop All LSP Servers',
      message: 'This will stop all running language servers. Continue?',
      confirmText: 'Stop All',
      variant: 'danger',
    });

    if (!confirmed) return;

    try {
      const count = await lspClient.stopAllServers();
      if (count > 0) {
        loadStatus();
      }
    } catch (e) {
      await alert({
        title: 'Error',
        message: e instanceof Error ? e.message : 'Failed to stop servers',
      });
    }
  }, [lspClient, loadStatus, confirm, alert]);

  // Group instances by server name
  const instancesByServer = React.useMemo(() => {
    if (!status?.runningInstances) return new Map<string, LSPServerInstance[]>();

    const grouped = new Map<string, LSPServerInstance[]>();
    for (const instance of status.runningInstances) {
      const server = instance.serverName;
      if (!grouped.has(server)) {
        grouped.set(server, []);
      }
      grouped.get(server)!.push(instance);
    }
    return grouped;
  }, [status?.runningInstances]);

  // Counts for header
  const configuredCount = status?.configuredServers.length || 0;
  const runningCount = status?.runningInstances.length || 0;

  // No client provided
  if (!lspClient) {
    return null;
  }

  return (
    <section className="supervisor-section lsp-section">
      <div
        className="supervisor-section__header lsp-section__header"
        onClick={onToggleCollapse}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            onToggleCollapse?.();
          }
        }}
      >
        <span className="supervisor-section__icon">{'\u{1F524}'}</span>
        <span className="supervisor-section__title">LANGUAGE SERVERS</span>
        <span className="supervisor-section__count">
          ({configuredCount} configured{runningCount > 0 ? `, ${runningCount} running` : ''})
        </span>

        <div className="supervisor-section__action">
          {runningCount > 0 && (
            <ActionButton
              label="Stop All"
              onClick={handleStopAll}
              variant="danger"
            />
          )}
          <span className="lsp-section__collapse-icon">
            {isCollapsed ? '\u{25B6}' : '\u{25BC}'}
          </span>
        </div>
      </div>

      {!isCollapsed && (
        <div className="lsp-section__content">
          {isLoading ? (
            <div className="supervisor-loading">Loading LSP status...</div>
          ) : error ? (
            <div className="supervisor-error">
              <span className="supervisor-error__icon">{'\u{26A0}\uFE0F'}</span>
              <span className="supervisor-error__message">{error}</span>
              <ActionButton label="Retry" onClick={loadStatus} variant="primary" />
            </div>
          ) : status?.configuredServers.length === 0 ? (
            <div className="supervisor-empty">
              No language servers configured. Add servers to supervisor.yaml to enable LSP support.
            </div>
          ) : (
            <div className="lsp-servers-grid">
              {status?.configuredServers.map((config) => (
                <LSPServerConfigCard
                  key={config.name}
                  config={config}
                  instances={instancesByServer.get(config.name) || []}
                  onStart={handleStart}
                  onViewLogs={handleViewLogs}
                  onRestart={handleRestart}
                  onStop={handleStop}
                  restartingKeys={restartingKeys}
                  stoppingKeys={stoppingKeys}
                  isStarting={startingServers.has(config.name)}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Process Log Viewer Modal */}
      {viewingLogsInstance && supervisorClient && (
        <div className="supervisor-modal-overlay" onClick={handleCloseLogViewer}>
          <div className="supervisor-modal supervisor-modal--logs" onClick={(e) => e.stopPropagation()}>
            <ProcessLogViewer
              process={lspInstanceToProcessInfo(viewingLogsInstance)}
              client={supervisorClient}
              onClose={handleCloseLogViewer}
            />
          </div>
        </div>
      )}
    </section>
  );
}

/**
 * Convert an LSPServerInstance to a ProcessInfo for the log viewer.
 */
function lspInstanceToProcessInfo(instance: LSPServerInstance): ProcessInfo {
  return {
    processId: instance.processId,
    command: `LSP: ${instance.serverName}`,
    name: `${instance.serverName} (${instance.workspace.split('/').pop() || instance.workspace})`,
    host: 'local',
    sessionId: '', // Not used by log viewer
    status: instance.processStatus,
    processType: 'lsp',
  };
}

export default LSPSection;
