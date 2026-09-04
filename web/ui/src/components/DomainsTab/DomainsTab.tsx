/**
 * DomainsTab - Container for dynamically loaded domain plugin UIs
 *
 * This tab displays UIs from loaded domain plugins. When a domain with UI
 * is loaded, its component appears here.
 *
 * Features:
 * - Lists available plugins
 * - Loads plugin UIs on demand
 * - Renders plugin components with proper context
 * - Handles plugin load/unload lifecycle
 */

import React, { useState, useEffect, useCallback } from 'react';
import { usePlugins, pluginRegistry, type PluginInfo, type PluginContext, type ConfirmOptions } from '../../plugins';
import type { SessionDataServiceClient, DomainRpcServiceClient, SessionManagerServiceClient } from '../../../../generated/balloons-client';
import { useDialog } from '../Dialog/DialogContext';
import './DomainsTab.css';
import { createLogger } from '../../utils/debugLog';

const debugLog = createLogger('DomainsTab');

interface DomainsTabProps {
  /** Send a message to the LLM */
  sendMessage?: (message: string) => void;
  /** Current session ID */
  sessionId?: string;
  /** Session data service client for domain event subscriptions */
  sessionDataClient?: SessionDataServiceClient;
  /** Domain RPC service client for calling @ws_expose methods */
  domainRpcClient?: DomainRpcServiceClient;
  /** Session manager service client for loadDomain/unloadDomain */
  sessionsClient?: SessionManagerServiceClient;
  /** Whether the LLM is currently responding (streaming) */
  isLLMResponding?: boolean;
}

export function DomainsTab({
  sendMessage,
  sessionId,
  sessionDataClient,
  domainRpcClient,
  sessionsClient,
  isLLMResponding = false,
}: DomainsTabProps) {
  const { loaded, load, unload, isLoaded } = usePlugins();
  const { confirm: appConfirm } = useDialog();
  const [available, setAvailable] = useState<PluginInfo[]>([]);
  const [loading, setLoading] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [activePlugin, setActivePlugin] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  // Track which loaded plugins have newer builds available
  const [pluginsWithUpdates, setPluginsWithUpdates] = useState<Set<string>>(new Set());

  // Handle escape key to exit fullscreen
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isFullscreen) {
        setIsFullscreen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isFullscreen]);

  // Fetch available plugins
  const refreshAvailable = useCallback(async () => {
    const plugins = await pluginRegistry.listAvailable();
    setAvailable(plugins);
  }, []);

  // Check for updates to loaded plugins
  // Using a ref to avoid recreating the callback when `loaded` changes
  const loadedRef = React.useRef(loaded);
  loadedRef.current = loaded;

  const checkForUpdates = useCallback(async () => {
    const currentLoaded = loadedRef.current;
    if (currentLoaded.length === 0) return;

    const updates = new Set<string>();
    for (const plugin of currentLoaded) {
      const hasUpdate = await pluginRegistry.hasUpdate(plugin.id);
      if (hasUpdate) {
        updates.add(plugin.id);
      }
    }
    setPluginsWithUpdates(updates);
  }, []); // No dependencies - uses ref

  // Check for updates periodically (every 5 seconds in dev mode)
  useEffect(() => {
    // Only check if plugins are loaded
    if (loaded.length === 0) return;

    checkForUpdates();
    const interval = setInterval(checkForUpdates, 5000);
    return () => clearInterval(interval);
  }, [checkForUpdates, loaded.length]); // Only re-run when plugin count changes

  // Fetch on mount
  useEffect(() => {
    refreshAvailable();
  }, [refreshAvailable]);

  // Listen for backend domain_loaded / domain_unloaded events to auto-load/unload UI plugins
  useEffect(() => {
    if (!sessionDataClient) return;

    const unsubscribe = sessionDataClient.sessionDataDomainEvent((event) => {
      // System-level domain events (load/unload)
      if (event.domainId === 'system') {
        const data = event.data as { domainId?: string };
        const domainId = data.domainId;

        if (!domainId) return;

        if (event.eventType === 'domain_loaded') {
          debugLog(`Backend loaded domain: ${domainId}, auto-loading UI`);
          // Check if UI plugin exists and isn't already loaded
          if (!isLoaded(domainId)) {
            load(domainId).catch(err => {
              console.warn(`[DomainsTab] Failed to auto-load UI for ${domainId}:`, err);
            });
          }
          // Refresh available list
          refreshAvailable();
        } else if (event.eventType === 'domain_unloaded') {
          debugLog(`Backend unloaded domain: ${domainId}, auto-unloading UI`);
          // Unload UI plugin if loaded
          if (isLoaded(domainId)) {
            unload(domainId);
          }
          // Refresh available list
          refreshAvailable();
        }
      }
    });

    return unsubscribe;
  }, [sessionDataClient, load, unload, isLoaded, refreshAvailable]);

  // Reload a plugin (unload then load to get new version)
  // Also reloads the server-side domain to pick up Python code changes
  const handleReload = async (pluginId: string) => {
    if (loading.has(pluginId)) return;

    setLoading(prev => new Set(prev).add(pluginId));
    setError(null);

    try {
      // First, reload the server-side domain (picks up Python code changes)
      if (sessionDataClient) {
        debugLog(`Reloading server-side domain: ${pluginId}`);
        const result = await sessionDataClient.reloadDomain(pluginId);
        debugLog(`Server reload result:`, result);
      }

      // Then reload the UI
      unload(pluginId);
      // Refresh available to get updated manifest with new builtAt
      await refreshAvailable();
      await load(pluginId);
    } catch (err) {
      setError(`Failed to reload ${pluginId}: ${err}`);
    } finally {
      setLoading(prev => {
        const next = new Set(prev);
        next.delete(pluginId);
        return next;
      });
    }
  };

  // Wrapper for confirm that adapts to plugin interface
  const pluginConfirm = useCallback(async (options: ConfirmOptions): Promise<boolean> => {
    return appConfirm({
      ...options,
      message: options.message,
    });
  }, [appConfirm]);

  // Use refs to keep callback functions stable while still having access to latest values
  const sessionIdRef = React.useRef(sessionId);
  const sessionDataClientRef = React.useRef(sessionDataClient);
  const domainRpcClientRef = React.useRef(domainRpcClient);
  sessionIdRef.current = sessionId;
  sessionDataClientRef.current = sessionDataClient;
  domainRpcClientRef.current = domainRpcClient;

  // Stable callback functions that use refs
  const subscribeToDomainEvents = React.useCallback(
    (domainId: string, callback: (event: any) => void) => {
      const client = sessionDataClientRef.current;
      if (!client) return () => {};
      return client.sessionDataDomainEvent((event) => {
        if (event.domainId === domainId) {
          callback(event);
        }
      });
    },
    []
  );

  const requestDomainState = React.useCallback(
    async (domainId: string) => {
      const client = sessionDataClientRef.current;
      const sid = sessionIdRef.current;
      if (!client || !sid) return false;
      return client.requestDomainState(sid, domainId);
    },
    []
  );

  const callDomainMethod = React.useCallback(
    async (methodName: string, params?: Record<string, unknown> | null) => {
      const client = domainRpcClientRef.current;
      const sid = sessionIdRef.current;
      if (!client) return { error: 'No RPC client' };
      if (!sid) return { error: 'No session' };
      return client.callDomainMethod(methodName, sid, params);
    },
    []
  );

  // Create context for plugin components
  const createPluginContext = useCallback((): PluginContext => {
    return {
      sendMessage,
      sessionId,
      isLLMResponding,
      confirm: pluginConfirm,
      subscribeToDomainEvents: sessionDataClient ? subscribeToDomainEvents : undefined,
      requestDomainState: sessionDataClient ? requestDomainState : undefined,
      callDomainMethod: domainRpcClient ? callDomainMethod : undefined,
    };
  }, [sendMessage, sessionId, sessionDataClient, domainRpcClient, isLLMResponding, pluginConfirm, subscribeToDomainEvents, requestDomainState, callDomainMethod]);

  // Handle loading a plugin (loads both backend domain and frontend UI)
  const handleLoad = async (pluginId: string) => {
    if (loading.has(pluginId)) return;

    setLoading(prev => new Set(prev).add(pluginId));
    setError(null);

    try {
      // Load backend domain first (if sessionsClient available)
      // This will emit domain_loaded event which triggers auto-load of UI
      if (sessionsClient) {
        debugLog(`Loading backend domain: ${pluginId}`);
        await sessionsClient.loadDomain(pluginId, sessionId || undefined);
      }
      // Load frontend UI
      await load(pluginId);
      setActivePlugin(pluginId);
    } catch (err) {
      setError(`Failed to load ${pluginId}: ${err}`);
    } finally {
      setLoading(prev => {
        const next = new Set(prev);
        next.delete(pluginId);
        return next;
      });
    }
  };

  // Handle unloading a plugin (unloads both backend domain and frontend UI)
  const handleUnload = async (pluginId: string) => {
    // Unload backend domain first (if sessionsClient available)
    // This will emit domain_unloaded event
    if (sessionsClient) {
      debugLog(`Unloading backend domain: ${pluginId}`);
      await sessionsClient.unloadDomain(pluginId, sessionId || undefined);
    }
    // Unload frontend UI
    unload(pluginId);
    if (activePlugin === pluginId) {
      // Switch to another loaded plugin or null
      const remaining = loaded.filter(p => p.id !== pluginId);
      const nextPlugin = remaining[0];
      setActivePlugin(nextPlugin ? nextPlugin.id : null);
    }
  };

  // Get the active plugin's component
  const activePluginManifest = loaded.find(p => p.id === activePlugin);
  const PluginComponent = activePluginManifest?.component;

  return (
    <div className={`domains-tab ${isFullscreen ? 'domains-tab--fullscreen' : ''}`}>
      {/* Plugin selector bar */}
      <div className="domains-plugin-bar">
        <div className="domains-loaded-plugins">
          {loaded.map(plugin => (
            <button
              key={plugin.id}
              className={`domains-plugin-button ${activePlugin === plugin.id ? 'active' : ''} ${pluginsWithUpdates.has(plugin.id) ? 'has-update' : ''}`}
              onClick={() => setActivePlugin(plugin.id)}
            >
              {plugin.tab?.icon && <span className="plugin-icon">{plugin.tab.icon}</span>}
              {plugin.tab?.label || plugin.name}
              {pluginsWithUpdates.has(plugin.id) && (
                <span className="plugin-update-dot" title="New build available - click ↻ to reload">●</span>
              )}
              <span
                className="plugin-reload"
                onClick={(e) => {
                  e.stopPropagation();
                  handleReload(plugin.id);
                  // Clear update indicator
                  setPluginsWithUpdates(prev => {
                    const next = new Set(prev);
                    next.delete(plugin.id);
                    return next;
                  });
                }}
                title="Reload plugin (get latest version)"
              >
                ↻
              </span>
              <span
                className="plugin-close"
                onClick={(e) => {
                  e.stopPropagation();
                  handleUnload(plugin.id);
                }}
                title="Unload plugin"
              >
                ×
              </span>
            </button>
          ))}
        </div>

        <div className="domains-available-plugins">
          <select
            value=""
            onChange={(e) => {
              if (e.target.value) {
                handleLoad(e.target.value);
              }
            }}
          >
            <option value="">+ Load Plugin...</option>
            {available
              .filter(p => !isLoaded(p.id))
              .map(p => (
                <option key={p.id} value={p.id} disabled={loading.has(p.id)}>
                  {p.id} {loading.has(p.id) ? '(loading...)' : ''}
                </option>
              ))}
          </select>
        </div>

        {/* Fullscreen toggle - show when any plugins are loaded */}
        {loaded.length > 0 && (
          <button
            className="domains-fullscreen-button"
            onClick={() => setIsFullscreen(!isFullscreen)}
            title={isFullscreen ? 'Exit fullscreen (Esc)' : 'Enter fullscreen'}
          >
            {isFullscreen ? '⤓' : '⤢'}
          </button>
        )}
      </div>

      {/* Error message */}
      {error && (
        <div className="domains-error">
          {error}
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      {/* Plugin content area */}
      <div className="domains-content">
        {PluginComponent ? (
          <PluginComponent {...createPluginContext()} />
        ) : loaded.length === 0 ? (
          <div className="domains-empty">
            <h3>No Plugins Loaded</h3>
            <p>Select a plugin from the dropdown above to load it.</p>
            {available.length > 0 && (
              <div className="domains-available-list">
                <h4>Available Plugins:</h4>
                <ul>
                  {available.map(p => (
                    <li key={p.id}>
                      <button
                        onClick={() => handleLoad(p.id)}
                        disabled={loading.has(p.id)}
                      >
                        {p.id}
                      </button>
                      <span className="plugin-version">v{p.manifest.version}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <div className="domains-empty">
            <p>Select a loaded plugin from the tabs above.</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default DomainsTab;
